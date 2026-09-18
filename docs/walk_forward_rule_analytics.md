# Walk-forward rule performance analytics

The unified MCP exposes two read-only analytics actions for event-sourced causal walk-forward experiments:

- summarize_walk_forward_rule_performance
- summarize_walk_forward_periodic_review

Both actions verify the full authoritative JSONL hash chain before reporting. They never append events, record reviews, learn/refine/retire rules, alter equity, or backdate causal state.

## Rule performance

summarize_walk_forward_rule_performance supports:

- ENTRY, VETO, FLIP, or ALL family filtering;
- exact rule ID + version attribution;
- lifecycle/deployment status;
- lifetime, selected-range, last-month, last-3-month, and since-last-periodic-review windows;
- wins, losses, breakevens, win rate, 95% Wilson interval, net R, average R, gross profit/loss R, profit factor, and loss streaks;
- LOW_SAMPLE / MODERATE_SAMPLE / MATURE_SAMPLE labels;
- rule-family lifetime aggregation across versions;
- per-trade matched ENTRY/VETO/FLIP rule-version attribution;
- overlap-aware ENTRY statistics, including rule-only trades, shared trades, overlap partners, and common ENTRY combinations;
- descriptive degradation flags without any automatic rule mutation.

Rule performance is association performance. When one resolved trade matches multiple ENTRY rules, it remains one unique trade; the same outcome can be associated with several rules and must not be interpreted as independent evidence.

### Version attribution

Historical candidate captures store matched Strategy Builder group IDs. Analytics reconstructs the exact active immutable rule version at the candidate capture sequence. A refinement such as ENTRY_006 v3 therefore does not inherit v1/v2 trade outcomes into its own version statistics.

Family-level statistics can still aggregate the full ENTRY_006 history across all versions.

## VETO effectiveness

Vetoed opportunities are intentionally not persisted as resolved WF trades. To measure VETO quality without mutating the ledger, the analytics action performs a read-only causal replay against the immutable Every Viable Entry reference artifacts.

The replay:

1. starts no earlier than the first VETO effective-from time;
2. evaluates only rule versions active at each historical decision time;
3. requires an active ENTRY match before treating a row as a blockable opportunity;
4. excludes periods where WAIT_UNTIL_CLOSED had an open WF trade;
5. respects overlapping VETOs;
6. respects an active FLIP when a unique opposite-side EVE outcome exists;
7. reports an unresolved FLIP counterfactual rather than guessing when the opposite outcome is unavailable.

For every VETO/version it reports blocked opportunities, resolved/unresolved counterfactuals, losses avoided, wins blocked, precision, hypothetical net R, net R saved, VETO-only opportunities, shared VETO opportunities, and the same time windows used by ENTRY analytics.

## Periodic review packet

summarize_walk_forward_periodic_review produces evidence for ChatGPT's causal review judgment. It compares the most recent N-month period with the preceding equal-length period and returns:

- W/L, win rate, net R, average R, and profit factor;
- monthly performance;
- profile and regime performance;
- per-rule current-vs-previous period deltas;
- objectively improving/deteriorating average-R flags;
- newly learned rules;
- low-sample rules;
- VETO effectiveness for both periods;
- the current periodic-review anchor and whether its next due time has been reached.

The action does not record REVIEW_COMPLETED. The normal review action remains responsible for the causal judgment and any prospective rule events.

## Sample-strength labels

- LOW_SAMPLE: 0-9 resolved observations
- MODERATE_SAMPLE: 10-29 resolved observations
- MATURE_SAMPLE: 30+ resolved observations

These labels are evidence-strength hints only.

## MCP schema refresh

Because this change adds two registered MCP actions, restart the local MCP server after pulling the change and reconnect the Crypto Strategy Lab plugin once so ChatGPT receives the updated tool schema.
