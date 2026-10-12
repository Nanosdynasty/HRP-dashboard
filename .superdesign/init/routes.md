# Routes

| Route | Entry | Layout |
| --- | --- | --- |
| `/` | `static/index.html`, `static/js/app.js` | Client-selected dashboard workspace surface |
| `/api/news` | `app.py` | Cached, commercially screened news JSON |
| `/api/news/refresh` | `app.py` | Server refresh action |

News Intelligence is a workspace mode on `/`, rather than a separate URL.
