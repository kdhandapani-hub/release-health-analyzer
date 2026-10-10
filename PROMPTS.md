## Prompt
Verification: show an hourly table for Oct 9 from 08:00 to 20:00 UTC with: PAYQRY01 avg_elapsed_ms, payments API pass rate and p95 latency, and payment-events max lag. I need the sequence to be visibly staggered: DB degrades first, API about 1 hour later, Kafka lag building 1–2 hours after that. If they all change in the same hour, adjust the generator to stagger them and re-run.

From now on, append each prompt I send and a one-line outcome to PROMPTS.md.

Outcome: Staggered DB/API/Kafka degradation to 11:00/12:00/13:00 UTC, ended the incident at 20:00, regenerated the CSVs, and verified the hourly metrics.

## Prompt
Two refinements, then show the Oct 9 hourly table for 08:00–23:00:
1. Recovery should mirror the onset: DB recovers at 20:00, API by ~21:00, and payment-events lag drains gradually over 2–3 hours afterward instead of dropping instantly.
2. Baseline payments pass rate should stay within ~97–99% outside the incident (currently 91.7% at 08:00). Either increase payments test runs per hour or lower the baseline random failure rate.

Outcome: Set DB/API recovery to 20:00/21:00, drained Kafka lag across 20:00–22:00, and stabilized baseline payments pass rate at 98.0% with 102 tests per hour.

## Prompt
Small data tweak first: let the baseline payments pass rate vary naturally between ~97% and 99.5% hour to hour instead of a flat 98.0%. Keep the incident unchanged. Regenerate.

Then build the app. Create app.py with Streamlit, pandas and Plotly, following SPEC.md:
- Folder structure from section 5 (data/, analysis/, views/), with data loading cached via st.cache_data.
- Sidebar filters from section 4.1, but skip the "Infra tier" filter for now.
- Tabs from section 4.2. Fully build ONLY tab 1 (Overview): KPI cards grouped by layer (API, Messaging, Database) with units and delta vs. the previous baseline, plus a green/amber/red health indicator per layer. Skip the Infrastructure KPIs. Every other tab shows "Coming soon" for now.
- Filters must apply to the Overview.
- Configure the Replit run command so the Run button launches the Streamlit app and it shows in Preview.

Outcome: Regenerated data with varied baseline payments pass rates, built and verified the filtered Streamlit Overview and placeholder tabs, and configured the Run button and Preview workflow.

## Prompt
Change the default date range to the full 14 days.

Then build tab 2 (API Test Results) per SPEC.md section 4.2:
- Pass rate by service and by endpoint (bar charts, %).
- Latency distribution with p50/p95/p99 (ms).
- Failure reasons breakdown (count and %).
- Release-over-release comparison table: pass rate and p95 per release_tag, with delta vs. the previous release.
All charts must respect the sidebar filters, have titles and axis labels with units. Keep logic in analysis/ and the view in views.

Outcome: Set the default range to Oct 1–14, 2026 and built the filtered API Test Results tab with pass-rate, latency percentile, failure-reason, and release comparison views; verified aggregations and zero Streamlit exceptions.

## Prompt
On the API Test Results tab, add a dashed reference line at the 98% SLA labeled "SLA 98%" on both pass-rate charts, and color bars by status: green ≥98%, amber 95–98%, red <95%. Define the SLA and threshold values once in analysis/ and reuse them for the Overview health badges so status is consistent across the app.

Outcome: Centralized the 98% SLA and 95% warning cutoff, reused the pass-rate classifier for API bar colors and Overview health, added dashed SLA lines to both charts, and verified threshold boundaries and app rendering.
