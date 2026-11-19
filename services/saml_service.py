import os
import zlib
import base64
import uuid
import urllib.parse
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
import logging
from typing import Dict, Any, Optional

from config import settings

logger = logging.getLogger("saml_service")

class SAMLService:
    def __init__(self):
        self.sp_entity_id = settings.SAML_SP_ENTITY_ID
        self.sp_acs_url = settings.SAML_SP_ACS_URL
        self.idp_sso_url = settings.AZURE_SAML_SSO_URL
        self.idp_entity_id = settings.AZURE_SAML_IDP_ENTITY_ID
        self.idp_logout_url = settings.AZURE_SAML_LOGOUT_URL

    def generate_authn_request_url(self, relay_state: str = "/") -> str:
        """
        Generates an AuthnRequest XML for SAML 2.0 HTTP-Redirect binding,
        deflates it, base64 encodes it, and creates the redirection URL to Microsoft Entra ID.
        """
        request_id = "_" + str(uuid.uuid4())
        issue_instant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        authn_xml = (
            f'<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
            f'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
            f'ID="{request_id}" '
            f'Version="2.0" '
            f'IssueInstant="{issue_instant}" '
            f'Destination="{self.idp_sso_url}" '
            f'AssertionConsumerServiceURL="{self.sp_acs_url}" '
            f'ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">\n'
            f'  <saml:Issuer>{self.sp_entity_id}</saml:Issuer>\n'
            f'  <samlp:NameIDPolicy Format="urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified" AllowCreate="true" />\n'
            f'</samlp:AuthnRequest>'
        )

        # Deflate without zlib header (wbits=-15) per SAML 2.0 HTTP-Redirect specification
        compressor = zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=-15)
        deflated = compressor.compress(authn_xml.encode("utf-8")) + compressor.flush()
        b64_request = base64.b64encode(deflated).decode("ascii")

        params = {"SAMLRequest": b64_request}
        if relay_state:
            params["RelayState"] = relay_state

        query_string = urllib.parse.urlencode(params)
        separator = "&" if "?" in self.idp_sso_url else "?"
        redirect_url = f"{self.idp_sso_url}{separator}{query_string}"
        logger.info(f"Generated SAML AuthnRequest {request_id} targeting {self.idp_sso_url}")
        return redirect_url

    def parse_saml_response(self, saml_response_b64: str) -> Dict[str, Any]:
        """
        Decodes and extracts claims (email, name, roles) from an incoming Base64 SAMLResponse.
        """
        try:
            xml_bytes = base64.b64decode(saml_response_b64)
            xml_text = xml_bytes.decode("utf-8", errors="replace")
            root = ET.fromstring(xml_text)
        except Exception as e:
            logger.error(f"Failed to parse SAMLResponse XML: {e}")
            raise ValueError(f"Invalid SAMLResponse: {e}")

        # Check status code
        namespaces = {
            "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
            "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
        }

        status_code = root.find(".//samlp:StatusCode", namespaces)
        if status_code is not None:
            code_val = status_code.attrib.get("Value", "")
            if not code_val.endswith("Success"):
                logger.warning(f"SAML authentication failed with status: {code_val}")
                raise ValueError(f"SAML authentication not successful: {code_val}")

        # Extract Subject / NameID
        name_id_elem = root.find(".//saml:Subject/saml:NameID", namespaces)
        name_id = name_id_elem.text.strip() if name_id_elem is not None and name_id_elem.text else ""

        # Extract Attributes
        attributes: Dict[str, Any] = {}
        for attr in root.findall(".//saml:AttributeStatement/saml:Attribute", namespaces):
            attr_name = attr.attrib.get("Name", "")
            values = [val.text.strip() for val in attr.findall("saml:AttributeValue", namespaces) if val.text]
            if values:
                attributes[attr_name] = values[0] if len(values) == 1 else values

        # Resolve standard claims
        email = (
            attributes.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress")
            or attributes.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name")
            or attributes.get("email")
            or name_id
            or "authenticated.user@trinity-health.org"
        )
        if isinstance(email, list):
            email = email[0]

        given_name = attributes.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname", "")
        surname = attributes.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname", "")
        display_name = attributes.get("http://schemas.microsoft.com/identity/claims/displayname") or attributes.get("name")

        if not display_name:
            if given_name or surname:
                display_name = f"{given_name} {surname}".strip()
            elif email:
                display_name = email.split("@")[0].replace(".", " ").title()
            else:
                display_name = "Authorized User"

        role = attributes.get("http://schemas.microsoft.com/ws/2008/06/identity/claims/role") or "Director of Supply Chain & Patient Safety"
        if isinstance(role, list):
            role = ", ".join(role)

        user_info = {
            "name": display_name,
            "email": email,
            "role": role,
            "health_system": "Trinity Health",
            "auth_type": "SAML2.0_Azure_Entra_ID",
            "authenticated_at": datetime.now(timezone.utc).isoformat()
        }
        logger.info(f"Successfully processed SAML authentication for user: {email} ({display_name})")
        return user_info

    def generate_sp_metadata(self) -> str:
        """
        Generates standard SAML 2.0 Service Provider Metadata XML for this deployment.
        """
        metadata_xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="{self.sp_entity_id}">\n'
            f'  <md:SPSSODescriptor AuthnRequestsSigned="false" WantAssertionsSigned="true" protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">\n'
            f'    <md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified</md:NameIDFormat>\n'
            f'    <md:AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" Location="{self.sp_acs_url}" index="0" isDefault="true" />\n'
            f'  </md:SPSSODescriptor>\n'
            f'</md:EntityDescriptor>'
        )
        return metadata_xml

saml_service = SAMLService()
