package com.mneme.dto;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.DeserializationContext;
import com.fasterxml.jackson.databind.JsonDeserializer;
import com.fasterxml.jackson.databind.JsonNode;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

/** Normalize old CSV citations when replaying persisted conversations. */
public final class VisualRegionDeserializer extends JsonDeserializer<List<Double>> {
    @Override
    public List<Double> deserialize(JsonParser parser, DeserializationContext context) throws IOException {
        JsonNode node = parser.getCodec().readTree(parser);
        List<Double> values = new ArrayList<>();
        try {
            if (node.isTextual()) {
                for (String part : node.asText().split(",", -1)) values.add(Double.parseDouble(part.trim()));
            } else if (node.isArray()) {
                for (JsonNode item : node) {
                    if (!item.isNumber() && !item.isTextual()) return null;
                    values.add(Double.parseDouble(item.asText().trim()));
                }
            } else return null;
        } catch (NumberFormatException error) {
            return null;
        }
        if (values.size() != 4 || values.stream().anyMatch(value -> !Double.isFinite(value) || value < 0 || value > 1)) return null;
        if (values.get(0) > values.get(2) || values.get(1) > values.get(3)) return null;
        return List.copyOf(values);
    }
}
