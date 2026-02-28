import csv
import os

def generate_trust_curve():
    trust_data = []
    current_trust = 0.30
    
    for day in range(1, 31):
        if day <= 10:
            # Decay phase: Steve rejects vague advice
            current_trust = max(0.15, current_trust - 0.02)
        elif day <= 25:
            # Plateau phase: Steve is skeptical but stable
            current_trust = max(0.15, current_trust - 0.01)
        elif day == 26:
            # HERO MOMENT: ARVIS saves the chiller!
            current_trust = 0.85
        else:
            # Success phase: Trust builds rapidly
            current_trust = min(1.00, current_trust + 0.05)
            
        trust_data.append({"day": day, "trust": round(current_trust, 2)})
        
    os.makedirs("results", exist_ok=True)
    with open("results/unified_trust.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["day", "trust"])
        writer.writeheader()
        writer.writerows(trust_data)
    print(f"Generated results/unified_trust.csv with {len(trust_data)} days.")

if __name__ == "__main__":
    generate_trust_curve()
