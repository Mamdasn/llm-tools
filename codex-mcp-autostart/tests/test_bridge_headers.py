"""Header regression tests for both supported MCP SDK transport generations."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge import BridgeProtocolHeaders
from mcp.shared.message import ClientMessageMetadata, SessionMessage

HAS_HEADER_METADATA = "headers" in ClientMessageMetadata.__dataclass_fields__
if HAS_HEADER_METADATA:
    from mcp_types import PROTOCOL_VERSION_META_KEY, jsonrpc_message_adapter
    from mcp.shared.inbound import encode_header_value
else:
    from mcp.types import JSONRPCMessage


def message(**fields):
    wire = json.dumps({"jsonrpc": "2.0", **fields})
    parsed = jsonrpc_message_adapter.validate_json(wire) if HAS_HEADER_METADATA else JSONRPCMessage.model_validate_json(wire)
    return SessionMessage(parsed)


class BridgeHeaderCompatibilityTests(unittest.TestCase):
    @unittest.skipIf(HAS_HEADER_METADATA, "SDK 1 compatibility path")
    def test_sdk_one_preserves_messages_for_transport_negotiation(self):
        bridge = BridgeProtocolHeaders()
        request = message(id=1, method="tools/list")
        request.metadata = ClientMessageMetadata(resumption_token="keep")
        self.assertIs(bridge.outgoing(request), request)
        bridge.observe_response(message(id=1, result={"tools": []}))


@unittest.skipUnless(HAS_HEADER_METADATA, "SDK 2 supplies per-message HTTP metadata")
class BridgeHeadersTests(unittest.TestCase):
    def test_negotiation_preserves_wire_request_and_existing_metadata(self):
        bridge = BridgeProtocolHeaders()
        initialize = message(id=17, method="initialize", params={"protocolVersion": "2025-11-25"})
        self.assertIs(bridge.outgoing(initialize), initialize)
        bridge.observe_response(message(id=18, result={"protocolVersion": "wrong-request"}))
        self.assertIsNone(bridge.protocol_version)
        bridge.observe_response(message(id=17, result={"protocolVersion": "2025-06-18"}))

        request = message(id="tool-request", method="tools/call", params={"name": "résumé", "arguments": {"x": 3}})
        original_wire = request.message.model_dump()
        request.metadata = ClientMessageMetadata(resumption_token="token", headers={"x-example": "keep"})
        forwarded = bridge.outgoing(request)
        self.assertIs(forwarded.message, request.message)
        self.assertEqual(forwarded.message.model_dump(), original_wire)
        self.assertEqual(forwarded.metadata.resumption_token, "token")
        self.assertEqual(forwarded.metadata.headers, {
            "x-example": "keep", "mcp-protocol-version": "2025-06-18",
            "mcp-method": "tools/call", "mcp-name": encode_header_value("résumé"),
        })
        self.assertEqual(request.metadata.headers, {"x-example": "keep"})

    def test_modern_envelope_supplies_version_without_handshake(self):
        bridge = BridgeProtocolHeaders()
        request = message(id=4, method="resources/read", params={
            "uri": "memory://personal", "_meta": {PROTOCOL_VERSION_META_KEY: "2026-07-28"},
        })
        forwarded = bridge.outgoing(request)
        self.assertIs(forwarded.message, request.message)
        self.assertEqual(forwarded.metadata.headers, {
            "mcp-protocol-version": "2026-07-28", "mcp-method": "resources/read",
            "mcp-name": "memory://personal",
        })

    def test_notification_and_response_keep_negotiated_version(self):
        bridge = BridgeProtocolHeaders()
        bridge.protocol_version = "2025-11-25"
        initialized = bridge.outgoing(message(method="notifications/initialized"))
        self.assertEqual(initialized.metadata.headers["mcp-protocol-version"], "2025-11-25")
        response = bridge.outgoing(message(id=91, result={"roots": []}))
        self.assertEqual(response.metadata.headers, {"mcp-protocol-version": "2025-11-25"})


if __name__ == "__main__":
    unittest.main()
