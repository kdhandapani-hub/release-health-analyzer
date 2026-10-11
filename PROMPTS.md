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

## Prompt
Build tab 3 (Event Stream Health) per SPEC.md section 4.2:
- Lag heatmap: topic/partition (y) × time (x), color = lag in messages.
- Throughput trend (msgs/sec) per topic over time.
- Top lagging consumer groups table: max lag, avg lag, and peak time.
- Error rate (%) by topic over time.

Consistency with the API tab:
- Define lag and error-rate thresholds (healthy / warning / critical) in the same shared analysis/ thresholds module used for the 98% API SLA, and use them for the Overview Messaging badge too.
- Use the exact same green / amber / red status colors as the API pass-rate charts for the table status and any threshold lines (e.g., a dashed warning/critical line on the error-rate chart).
- The heatmap can use a continuous color scale, but it should run from neutral/cool to the same red at the critical lag threshold.

All charts respect the sidebar filters, with titles, axis labels and units. Use horizontal x-axis time labels every 6 hours. Keep logic in analysis/ and the view in views/.

Outcome: Built Event Stream Health with filtered lag heatmap, topic throughput/error-rate trends, and a status-colored consumer-group table; centralized messaging thresholds and verified 6-hour chart ticks and app rendering.

## Prompt
Fixes for the Event Stream Health tab (and apply the axis fix app-wide):
1. X-axis time labels are overlapping and unreadable. Make them horizontal and adapt tick spacing to the selected range: every 3–6 hours for a 1-day range, one tick per day (e.g. "Oct 3") for multi-day ranges. Apply this to all time-series charts in every tab.
2. Round avg lag to whole messages in the top-lagging table.
3. Heatmap color scale: replace the rainbow scale with a sequential scale from dark neutral (0) through amber (warning threshold) to the same red used for critical status (at the critical threshold). Low lag should stay dark and quiet.
Then show me the tab with the date range set to Oct 9 only.

Outcome: Added horizontal date-aware axes across Overview and Event Stream charts, rounded displayed average lag, changed the heatmap scale to dark-neutral/amber/red, and showed Event Stream with Oct 9 selected while retaining the full-range default.

## Prompt
Build tab 4 (Database Health) per SPEC.md section 4.2:
- DB time by connection user: split by caller type (API vs Consumer) per service, as a stacked bar or grouped bar (total elapsed time = executions × avg_elapsed_ms, shown in seconds).
- Top SQL table: sql_id, db_user(s), sql_type, executions, avg elapsed (ms), max elapsed (ms), top wait class, and status.
- Elapsed-time trend per SQL ID over time (ms), with the top 5 SQL by elapsed time shown and the rest hidden by default.
- Wait class breakdown over time (% of DB time by wait class, stacked area).
- Plan change detection: a table flagging any SQL whose plan_hash_value changed in the selected range AND whose avg elapsed time regressed. Show sql_id, old plan, new plan, change time, elapsed before → after (ms), and regression factor (e.g., 7.2x).
- Add vertical change-event markers (from change_events.csv, labeled with change_id) on the elapsed-time and wait-class charts.

Also fix the Overview Database section: add a "Slowest SQL elapsed (ms)" card showing the worst sql_id, and plot slowest-SQL elapsed alongside the average in the Overview database trend so a 7x regression is obvious.

Consistency: use the shared analysis/ thresholds module for DB elapsed-time warning/critical levels, the same green/amber/red status colors, and the same adaptive horizontal x-axis labels as the other tabs. Respect all sidebar filters, including Caller type and DB instance. Keep logic in analysis/ and the view in views/.

## Outcome
Built the filtered Database Health tab with DB-time bars, SQL summary/trends, wait-share area, event markers, and plan-regression detection; added the Overview slowest-SQL KPI/trend. Verified PAYQRY01’s 7.7× regression, filter behavior, and clean app rendering.

## Prompt
Build tab 6 (Root Cause Correlation) per SPEC.md section 4.2, without the infrastructure lane for now:

1. Three time-aligned lanes sharing one x-axis (stacked subplots, shared zoom):
   - Database: slowest-SQL elapsed (ms) and average elapsed
   - API: failure rate (%) and p95 latency (ms) on a secondary axis
   - Messaging: max consumer lag (messages)
   Draw each layer's warning/critical thresholds from the shared thresholds module, and shade the periods where a layer is in breach using the shared status colors.
2. Vertical change-event markers labeled with change_id across all three lanes.
3. Deterministic root-cause logic in analysis/ (rule-based, no LLM):
   - For each layer, find the first hour it breaches its critical threshold in the selected range.
   - Order the layers by first breach time and show the sequence, e.g. "Database 11:00 → API 12:00 → Messaging 13:00".
   - Attribute the likely trigger to the most recent change event before the FIRST breach.
   - For every other change event in range, show whether it was "cleared" (no breach in any layer within 3 hours after it) or "inconclusive".
4. A summary panel at the top: likely trigger (change_id + type + time), first layer to degrade, sequence, time from change to first breach, and the list of cleared changes (e.g., R2026.10.09 cleared — no breach for 5 hours after deploy).
5. If no layer breaches in the selected range, show "No correlated degradation in this range."

Respect sidebar filters, use the same colors and adaptive horizontal x-axis labels, keep logic in analysis/ and the view in views/.

## Outcome
Built the three-lane filtered correlation view with shared thresholds, warning/critical shading, labeled change markers, and deterministic trigger/clearance summaries. Verified the Oct 9 chain (Database 11:00 → API 12:00 → Messaging 18:00 UTC), DBPATCH-1009 attribution, cleared app release, and 14-chart app render.
