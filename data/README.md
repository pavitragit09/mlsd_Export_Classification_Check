# Corpus Data Sources and Documentation

This directory contains the regulatory corpus used by the Export Classification Check Service.

## Scope
- Customs Tariff General Rules for Interpretation (GRI 1 through 6)
- Section XV Notes (Base Metals and Articles of Base Metal)
- Chapter 73: Articles of iron or steel (with Chapter Notes)
- Section XX Notes (Miscellaneous Manufactured Articles)
- Chapter 96: Miscellaneous manufactured articles (with Chapter Notes)
- DGFT Export Policy Schedule (Chapters 73 and 96)

## Official Source Links
1. **Customs Tariff General Rules for Interpretation (GRI)**
   - Official Publisher: Central Board of Indirect Taxes and Customs (CBIC), India
   - URL: https://www.cbic.gov.in/resources/htdocs-cbec/customs/cst2023-24/gri.pdf
   - Expected filename: `data/raw/gri_rules.pdf` or `data/raw/gri_rules.txt`

2. **Chapter 73 - Articles of Iron or Steel**
   - Official Publisher: CBIC
   - URL: https://www.cbic.gov.in/resources/htdocs-cbec/customs/cst2023-24/chap-73.pdf
   - Expected filename: `data/raw/chapter_73.pdf` or `data/raw/chapter_73.txt`

3. **Chapter 96 - Miscellaneous Manufactured Articles**
   - Official Publisher: CBIC
   - URL: https://www.cbic.gov.in/resources/htdocs-cbec/customs/cst2023-24/chap-96.pdf
   - Expected filename: `data/raw/chapter_96.pdf` or `data/raw/chapter_96.txt`

4. **DGFT Export Policy Schedule (Schedule 2 - Export Policy)**
   - Official Publisher: Directorate General of Foreign Trade (DGFT), Ministry of Commerce and Industry, India
   - URL: https://dgft.gov.in/CP/?opt=export-policy
   - Expected filename: `data/raw/dgft_export_policy.pdf` or `data/raw/dgft_export_policy.json`

## Sample Corpus (`data/sample/`)
A complete, structured, authentic sample corpus is provided under `data/sample/`:
- `gri.json`: Full text and rules for GRI 1, GRI 2(a/b), GRI 3(a/b/c), GRI 4, GRI 5(a/b), GRI 6.
- `section_notes.json`: Section XV notes (including Note 1(m) explicitly excluding goods of Chapter 96 e.g. vacuum flasks) and Section XX notes.
- `chapter_73.json`: Chapter notes and headings 7301 to 7326 (e.g. 7323 table, kitchen or household articles of iron/steel).
- `chapter_96.json`: Chapter notes and headings 9601 to 9620 (e.g. 9617 vacuum flasks and other vacuum vessels).
- `dgft_policy.json`: DGFT Export Policy rows for Chapters 73 and 96 (Free, Restricted, Prohibited conditions).

Running `python -m ingestion.ingest` loads from `data/sample/` (or downloaded raw files if present) and builds the FAISS indexes into `data/index/`.
