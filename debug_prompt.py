from agent_bms.prompt_builder import get_ops_prompt_builder, LAYER_TRUST_BOUNDARIES

builder = get_ops_prompt_builder()

print("--- DEBUG INFO ---")
print(f"LAYER_TRUST_BOUNDARIES length: {len(LAYER_TRUST_BOUNDARIES)}")
print(f"'trust_boundaries' in LAYERS: {'trust_boundaries' in builder.LAYERS}")
if 'trust_boundaries' in builder.LAYERS:
    content = builder.LAYERS['trust_boundaries']
    print(f"Content length in LAYERS: {len(content)}")
    print(f"Starts with: {content[:50]}")

print(f"'trust_boundaries' in LAYER_ORDER: {'trust_boundaries' in builder.LAYER_ORDER}")

prompt = builder.build_full_prompt()
print(f"Full prompt length: {len(prompt)}")
if "NEVER write to BACnet" in prompt:
    print("SUCCESS: Found text in prompt")
else:
    print("FAILURE: Text not found in prompt")
