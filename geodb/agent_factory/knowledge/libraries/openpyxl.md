# Excel Output Patterns

## Write DataFrame to Excel
```python
import pandas as pd
df.to_excel(output_path, index=False, sheet_name="Results")
```

## Write with formatting
```python
import openpyxl
from openpyxl.styles import Font, Alignment
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Results"
headers = ["point_id", "lat", "lon", "height_m"]
for ci, h in enumerate(headers, 1):
    cell = ws.cell(row=1, column=ci, value=h)
    cell.font = Font(bold=True)
for ri, row in enumerate(data, 2):
    for ci, val in enumerate(row, 1):
        ws.cell(row=ri, column=ci, value=val)
wb.save(output_path)
```
