# Theme

## Compact token summary

- Primary navy: `var(--hrp-navy)`; blue: `var(--hrp-blue)`; red accent: `#c44343`
- Background: `#f3f6f8`; surfaces: `#fff`; borders: `#dce3e8`
- Text: navy headings, muted greys for metadata
- Existing visual language: square-edged data cards, compact uppercase labels, restrained blue/red/teal category accents
- Existing News surface has a sticky white header and responsive layout under 900px.

## News styling source

Source: `static/css/style.css`, selectors `.news-surface` through `.news-empty`.

```css
.news-feed { display:grid; grid-template-columns:minmax(330px,1.3fr) minmax(290px,.7fr); gap:14px; padding:15px 28px 30px; }
.news-lead,.news-list,.news-empty { border:1px solid #dce3e8; background:#fff; box-shadow:0 5px 18px rgba(23,39,65,.06); }
.news-row { display:grid; gap:5px; padding:13px 16px; border-bottom:1px solid #e7ecef; }
```
