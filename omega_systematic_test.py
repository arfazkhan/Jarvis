import subprocess
import os
import time
import sys

def run_command(cmd, log_file):
    print(f"[{time.strftime('%H:%M:%S')}] Executing: {cmd}")
    print(f"[{time.strftime('%H:%M:%S')}] Logging to: {log_file}")
    
    with open(log_file, "w") as f:
        process = subprocess.Popen(cmd, shell=True, stdout=f, stderr=subprocess.STDOUT)
        process.wait()
        
    if process.returncode != 0:
        print(f"❌ Command failed with return code {process.returncode}")
        return False
    print("✅ Command successful.\n")
    return True

def main():
    print("Ω∞ — Systematic Comparative Test (BAU vs ARVIS)")
    print("=================================================")
    
    os.makedirs("logs", exist_ok=True)
    os.makedirs("results", exist_ok=True)
    
    # 1. BAU Baseline
    print("\n--- PHASE 1: BAU BASELINE ---")
    cmd_bau = "python simulation_omega_infinity.py --mode bau --turbo --days 30 --output_csv"
    if os.path.exists("logs/systematic_bau.log") and "Simulation Complete" in open("logs/systematic_bau.log").read():
        print("⏩ BAU Baseline already completed. Skipping.")
    else:
        if not run_command(cmd_bau, "logs/systematic_bau.log"):
            sys.exit(1)
        
    # 2. ARVIS Advisory (Skeptical Steve)
    print("\n--- PHASE 2: ARVIS ADVISORY (Skeptical Operator) ---")
    cmd_arvis = "python simulation_omega_infinity.py --mode arvis --persona skeptical_steve --turbo --days 30 --output_csv"
    if not run_command(cmd_arvis, "logs/systematic_arvis.log"):
        sys.exit(1)
        
    # 3. Generate Report
    print("\n--- PHASE 3: REPORT GENERATION ---")
    cmd_report = "python omega_v1_report_gen.py"
    if not run_command(cmd_report, "logs/systematic_report_gen.log"):
        sys.exit(1)
        
    # Rename report
    if os.path.exists("omega_v1_1_report.md"):
        try:
             os.remove("omega_systematic_report.md")
        except:
             pass
        os.rename("omega_v1_1_report.md", "omega_systematic_report.md")
        print("📄 Report generated: omega_systematic_report.md")
    
    print("\n✅ SYSTEMATIC TEST COMPLETE.")
    print("Artifacts:")
    print("- Logs: logs/systematic_bau.log, logs/systematic_arvis.log")
    print("- Data: results/unified_energy_bau.csv, results/unified_energy_arvis.csv")
    print("- Report: omega_systematic_report.md")

if __name__ == "__main__":
    main()
