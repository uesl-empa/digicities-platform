# Your Excel templates

Drop your filled-in copies of the Replica Builder Excel template into this folder. The "Bring your own template" section of [`../../09_excel_import.ipynb`](../../09_excel_import.ipynb) lists every `.xlsx` it finds here and lets you pick one to convert to TTL.

## Workflow

1. Copy the seed template to a new name in this folder:

   ```
   tutorial/sample_data/alpine_village_replica_template.xlsx
       → tutorial/sample_data/user_templates/<your_project>.xlsx
   ```

2. Open the copy in Excel / LibreOffice and replace the demo rows with your own components, attributes, and references.

3. In `09_excel_import.ipynb`, run the cells under **9.10 Bring your own template**. Your new file shows up in the dropdown.

4. The notebook writes `<your_project>.ttl` next to the `.xlsx` so the conversion output sits alongside the source.

## What's tracked

This folder itself (and `README.md` + `.gitkeep`) is committed so the directory exists for fresh clones. Your own `.xlsx` and generated `.ttl` files are git-ignored — see the root `.gitignore` rule.
