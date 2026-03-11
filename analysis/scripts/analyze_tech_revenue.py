"""Analyze 2023 Tech Revenue spreadsheet."""
import statistics

techs = ['Jesse', 'Danny', 'Dan', 'Neill', 'Tom', 'Alan', 'Kris']
q1 = [83337.5, 79232.5, 87756.5, 83987.5, 80957.5, 84202.5, 77045]
q2 = [83995, 77162.5, 94480, 72325, 87423, 83362.5, 56282.5]
q3 = [92467.5, 68411.75, 94567.5, 78102.5, 93575, 97236.25, 78782.5]
q4 = [71600, 97358.5, 96380, 91005, 84342.5, 96348.75, 80017.5]

print("=" * 95)
print("2023 TECH REVENUE — FULL ANALYSIS")
print("=" * 95)

# Annual totals table
header = f"{'Tech':<10} {'Q1':>12} {'Q2':>12} {'Q3':>12} {'Q4':>12} {'ANNUAL':>14} {'Avg/Qtr':>12}"
print(f"\n{header}")
print("-" * 95)

team_q = [0.0, 0.0, 0.0, 0.0]
annuals_list = []
for i, t in enumerate(techs):
    annual = q1[i] + q2[i] + q3[i] + q4[i]
    avg = annual / 4
    annuals_list.append((t, annual))
    print(f"{t:<10} ${q1[i]:>11,.2f} ${q2[i]:>11,.2f} ${q3[i]:>11,.2f} ${q4[i]:>11,.2f} ${annual:>13,.2f} ${avg:>11,.2f}")
    team_q[0] += q1[i]
    team_q[1] += q2[i]
    team_q[2] += q3[i]
    team_q[3] += q4[i]

team_total = sum(team_q)
print("-" * 95)
team_avg = team_total / 4
print(f"{'TEAM':<10} ${team_q[0]:>11,.2f} ${team_q[1]:>11,.2f} ${team_q[2]:>11,.2f} ${team_q[3]:>11,.2f} ${team_total:>13,.2f} ${team_avg:>11,.2f}")

per_tech_avg = team_total / 7
print(f"\nTeam total revenue: ${team_total:,.2f}")
print(f"Average per tech:   ${per_tech_avg:,.2f}")

# Rankings
print(f"\n\n{'='*50}")
print("ANNUAL RANKING (Highest to Lowest)")
print("=" * 50)
annuals_list.sort(key=lambda x: x[1], reverse=True)
for rank, (t, a) in enumerate(annuals_list, 1):
    pct = a / team_total * 100
    print(f"  {rank}. {t:<10} ${a:>12,.2f}  ({pct:.1f}% of team)")

spread = annuals_list[0][1] - annuals_list[-1][1]
print(f"\n  Spread (top - bottom): ${spread:,.2f}")

# Quarter-over-quarter trends
print(f"\n\n{'='*50}")
print("QUARTERLY TRENDS PER TECH")
print("=" * 50)
for i, t in enumerate(techs):
    quarters = [q1[i], q2[i], q3[i], q4[i]]
    best_q = quarters.index(max(quarters)) + 1
    worst_q = quarters.index(min(quarters)) + 1
    swing = max(quarters) - min(quarters)
    q4_vs_q1 = (q4[i] - q1[i]) / q1[i] * 100
    print(f"  {t:<10} Best: Q{best_q} (${max(quarters):>10,.0f}) | Worst: Q{worst_q} (${min(quarters):>10,.0f}) | Swing: ${swing:>10,.0f} | Q4 vs Q1: {q4_vs_q1:+.1f}%")

# Team quarterly trend
print("\n  TEAM quarterly totals:")
for qi in range(4):
    label = f"Q{qi+1}"
    per_tech = team_q[qi] / 7
    print(f"    {label}: ${team_q[qi]:>12,.0f}  (${per_tech:>10,.0f} per tech)")

for qi in range(1, 4):
    chg = (team_q[qi] - team_q[qi - 1]) / team_q[qi - 1] * 100
    print(f"    Q{qi+1} vs Q{qi}: {chg:+.1f}%")

# Consistency
print(f"\n\n{'='*50}")
print("CONSISTENCY (Lower CV = More Consistent)")
print("=" * 50)
consistency = []
for i, t in enumerate(techs):
    quarters = [q1[i], q2[i], q3[i], q4[i]]
    sd = statistics.stdev(quarters)
    mean = statistics.mean(quarters)
    cv = sd / mean * 100
    consistency.append((t, cv, sd, mean))

consistency.sort(key=lambda x: x[1])
for t, cv, sd, mean in consistency:
    print(f"  {t:<10} CV: {cv:>5.1f}%  (Avg ${mean:>10,.0f} | StdDev ${sd:>8,.0f})")

# Pay context
print(f"\n\n{'='*50}")
print("PAY CONTEXT (From Tracy)")
print("=" * 50)
alan_annual = q1[5] + q2[5] + q3[5] + q4[5]
print(f"  Alan 2023 annual revenue generated: ${alan_annual:,.2f}")
print(f"  Alan recent weekly pay example:     $3,033 for 47 hrs (${3033/47:.2f}/hr effective)")
print(f"  Tracy recent weekly pay example:    $2,463 for 88+ hrs (${2463/88:.2f}/hr effective)")
print("")
print("  Tech commission model: hours 'backed into' commission")
print("    Alan: $3,033 / 47 hrs = $64.53/hr effective rate")
print("    Tracy: $2,463 / 88 hrs = $27.99/hr effective rate")
print(f"    Tracy works {88/47:.1f}x Alan's hours, earns {2463/3033*100:.0f}% of his pay")
