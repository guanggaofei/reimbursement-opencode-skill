# Expense Screenshot Recognition Notes

Use these sample images only as visual references for the OCR organizer. The
actual matching logic should come from OCR text and invoice amounts, not from
image filenames.

## Screenshot Types

Classify each screenshot into one of these output suffixes:

- `支付记录`: payment-record screenshots from payment apps.
- `账单截图`: order/bill screenshots from shopping platforms.

Use these OCR text cues:

- If text contains `账单详情`, classify as `支付记录`.
- If a standalone line is `账单`, classify as `支付记录`.
- If text contains `支付成功`, usually classify as `支付记录`.
- If text contains `交易成功`, classify as `账单截图`.
- If text contains `实付款`, classify as `账单截图`.
- If no cue is clear, default to `支付记录` and leave uncertain matches for
  `待人工识别`.

## Amount Selection

Extract candidate amounts from OCR text.

- Prefer amounts with a minus sign or currency marker, such as `-18.90`,
  `¥83.10`, or `￥84.00`.
- Ignore amounts below `1.00` and above `10000.00`.
- For `账单截图`, the correct amount is often the amount near `实付款`.
- For `支付记录`, the correct amount is often the negative payment amount near
  the top of the screenshot.

## Matching Rules

Use the same conservative matching rules as `organize_expense_records.py`:

- If OCR text contains `出行`, `打车`, `滴滴`, or `花小猪`, treat the screenshot as
  taxi-related.
- For taxi-related screenshots, first match the amount against taxi trip-sheet
  line-item amounts, then map that trip item back to its taxi invoice.
- For non-taxi screenshots, match the amount against invoice total amounts.
- If exactly one invoice or trip item matches, copy the image to
  `支出记录整理/<分类>/`.
- If multiple candidates match, do not guess. Put the image in
  `支出记录整理/待人工识别/`.
- If no invoice or trip item matches, put the image in
  `支出记录整理/待人工识别/`.

## Output Names

For uniquely matched screenshots, use:

- `序号_价格_支付记录.jpg`
- `序号_价格_账单截图.jpg`

When the same invoice needs multiple screenshots of the same type, append
`_1`, `_2`, etc.

## Sample Files

- `alipay.jpg`: Alipay payment record. Text cue: `账单详情`. Example amount:
  `84.00`.
- `wechat.jpg`: WeChat payment record. Text cue: standalone `账单`. Example
  amount: `18.90`.
- `taobao.jpg`: Taobao order/bill screenshot. Text cue: `交易成功` and
  `实付款`. Example amount: `84.00`.
