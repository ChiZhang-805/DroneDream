import { assertEquals, assertThrows } from "jsr:@std/assert@1";

import { publicModelGatewayBaseUrl } from "../functions/model-gateway/index.ts";

Deno.test("managed-model grants use the public Supabase HTTPS function route", () => {
  assertEquals(
    publicModelGatewayBaseUrl("https://project.supabase.co"),
    "https://project.supabase.co/functions/v1/model-gateway",
  );
  assertEquals(
    publicModelGatewayBaseUrl("https://project.supabase.co/"),
    "https://project.supabase.co/functions/v1/model-gateway",
  );
});

Deno.test("managed-model public route rejects malformed Supabase URLs", () => {
  assertThrows(() => publicModelGatewayBaseUrl("not a URL"));
});
