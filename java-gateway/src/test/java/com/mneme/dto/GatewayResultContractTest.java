package com.mneme.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class GatewayResultContractTest {
    private final ObjectMapper mapper = new ObjectMapper().setSerializationInclusion(JsonInclude.Include.NON_NULL);

    private JsonNode schema() throws Exception {
        return mapper.readTree(Path.of("../contracts/gateway-result.schema.json").toFile());
    }

    @Test void sharedCasesAgreeWithBrowserIncludingNullableAndFalsyData() throws Exception {
        var schema = schema();
        var cases = mapper.readTree(Path.of("../contracts/gateway-result.cases.json").toFile());
        for (var item : cases) {
            assertEquals(item.path("valid").asBoolean(),
                SchemaContract.matches(schema, item.get("data"), mapper.createObjectNode()), item.path("id").asText());
        }
    }

    @Test void actualSuccessSerializationPreservesNullAndDataTypeEvenWithGlobalNonNullPolicy() throws Exception {
        var schema = schema();
        for (Object data : new Object[]{null, false, 0, "", List.of(), Map.of("id", 7)}) {
            var tree = mapper.readTree(mapper.writeValueAsString(Result.success(data)));
            assertTrue(SchemaContract.matches(schema, tree, mapper.createObjectNode()));
            assertEquals(200, tree.path("code").intValue());
            assertEquals("success", tree.path("message").textValue());
            assertTrue(tree.has("data"));
            assertEquals(mapper.valueToTree(data), tree.get("data"));
        }
    }

    @Test void actualErrorsPreserveCodeAndNullDataAndNullableReason() throws Exception {
        for (int code : new int[]{400, 401, 403, 404, 409, 413, 422, 429, 500, 502, 503, 504}) {
            for (String message : new String[]{null, "request failed"}) {
                var tree = mapper.readTree(mapper.writeValueAsString(Result.error(code, message)));
                assertTrue(SchemaContract.matches(schema(), tree, mapper.createObjectNode()));
                assertEquals(code, tree.path("code").intValue());
                assertEquals(mapper.valueToTree(message), tree.get("message"));
                assertTrue(tree.has("data") && tree.get("data").isNull());
            }
        }
    }

    @Test void unknownConstraintsFailClosedInBothContractKinds() {
        var schema = mapper.createObjectNode().put("format", "unknown");
        assertFalse(SchemaContract.matches(schema, mapper.valueToTree("anything"), mapper.createObjectNode()));
    }
}
