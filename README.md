# LServe
A Literature Survey Assistance Application.

## CLI Usage

LServe now provides a lightweight CLI to reduce repetitive paper collection work across journals.

```bash
python lserve.py search "graph neural networks" --journals "Nature,IEEE" --year-from 2020 --open-access --limit 10
python lserve.py add 1
python lserve.py add 2
python lserve.py list
python lserve.py citations --out citations.txt
python lserve.py download --dir downloads
```

### Features
- Search papers by keyword across journals (or filter to specific journals)
- Apply advanced filters (`--year-from`, `--year-to`, `--open-access`, `--limit`)
- Keep selected papers in a separate shortlist using `add`
- Export collected citations in one file
- Download all shortlisted paper files in one batch
