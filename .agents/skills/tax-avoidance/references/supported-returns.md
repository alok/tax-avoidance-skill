# Supported Returns

## Supported In V1

- 2025 federal individual returns
- Filing status: single or married filing jointly
- Income: W-2 wages, 1099-NEC contractor income, taxable interest, ordinary dividends, capital gains summaries, Social Security income, and common 1099-R retirement distributions when the taxable amount is available
- Common adjustments and deductions: IRA contribution tracking, HSA tracking, student loan interest, mortgage interest, charitable giving
- Common credits and review workflows: education-credit review, clean-energy review, clean-vehicle review
- Simple Schedule C skeletons for sole-proprietor contractor work when gross receipts are known and business expenses are supplied or explicitly treated as zero
- State data capture for resident state, work states, and follow-up notes, without automated state calculations yet
- Non-W-2 federal withholding capture from supported 1099 forms when the withholding field is available

## Supported Documents

- W-2
- 1099-INT
- 1099-DIV
- 1099-B summary data
- 1099-R
- 1098
- 1098-E
- 5498
- SSA-1099
- donation receipts

## Unsupported In V1

- automated state tax calculations
- rental properties
- K-1 partnership or S corp income
- options, RSUs, ESPP, or QSBS
- trust or estate filings
- multistate or international filings
- any concealment or falsification request

## Behavior On Unsupported Cases

Preserve the gathered facts, create `missing-items.md`, and state clearly that the flow is outside the supported simple-return envelope.
