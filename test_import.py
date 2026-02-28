try:
    from agent_commercial.bms_data_model import FailurePrediction
    print("Import successful: FailurePrediction found.")
except ImportError as e:
    print(f"Import failed: {e}")
except Exception as e:
    print(f"Other error: {e}")
