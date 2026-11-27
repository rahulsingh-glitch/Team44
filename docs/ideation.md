# Ideation Document — Team 44 · Track B

> Scored under **Business alignment (10)**. The solution must trace back to the
> problem statement and user value, with trade-offs explained.

## 1. The problem in our own words
<<After reading the card twice, restate the business pain in 2-3 sentences.>>

## 2. Who feels the pain, and the decision they can't make today
| Consumer | What they need | Decision it unblocks |
|---|---|---|
| <<e.g. Finance analyst>> | <<trusted daily totals>> | <<close the day's books>> |
| <<Category manager>> | <<margin by category>> | <<range/pricing calls>> |
| <<Store ops head>> | <<store ranking>> | <<staffing / interventions>> |

## 3. Options considered
| Option | Pros | Cons | Verdict |
|---|---|---|---|
| <<dbt+DuckDB>> | fast setup, SCD2+tests free | single-node | <<chosen>> |
| <<PySpark>> | scales, "data platform" | Windows/Hadoop setup cost | <<rejected for 5h window>> |

## 4. Chosen approach & why
<<One paragraph: the thinnest end-to-end slice that proves value, and why.>>

## 5. The thinnest end-to-end slice (must-have first)
<<Bronze→silver→gold→one mart→one dashboard tile, on one day of data.>>

## 6. Trade-offs we accepted
<<e.g. single-node engine; limited history window; simulated outbox.>>
