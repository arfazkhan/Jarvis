"""Test ML-powered tools integration"""
import asyncio
from agent_commercial.tools_schema import BMSToolHandler


async def test_ml_tools():
    handler = BMSToolHandler()
    
    print("=" * 60)
    print("Testing ML-Powered Tools")
    print("=" * 60)
    
    # Test detect_equipment_faults
    print("\n1. Testing detect_equipment_faults...")
    result = await handler.execute('detect_equipment_faults', {
        'equipment_id': 'AHU-01',
        'equipment_type': 'ahu',
    })
    
    print(f"   Equipment: {result.get('equipment_id')}")
    print(f"   Faults detected: {result.get('faults_detected')}")
    if 'interpretation' in result:
        print(f"   Interpretation verified: {result.get('interpretation_verified')}")
        print(f"   Interpretation: {result.get('interpretation')[:120]}...")
    elif 'error' in result:
        print(f"   Error: {result.get('error')}")
    
    # Test simulate_with_uncertainty
    print("\n2. Testing simulate_with_uncertainty...")
    result = await handler.execute('simulate_with_uncertainty', {
        'change_type': 'setpoint',
        'current_value': 22,
        'proposed_value': 24,
    })
    
    print(f"   Change: {result.get('change_type')} from {result.get('current_value')} to {result.get('proposed_value')}")
    if 'simulation' in result:
        sim = result.get('simulation', {})
        print(f"   Simulation result: {str(sim)[:100]}...")
    if 'interpretation' in result:
        print(f"   Interpretation verified: {result.get('interpretation_verified')}")
        print(f"   Interpretation: {result.get('interpretation')[:120]}...")
    elif 'error' in result:
        print(f"   Error: {result.get('error')}")
    
    print("\n" + "=" * 60)
    print("Tests complete!")


if __name__ == "__main__":
    asyncio.run(test_ml_tools())
