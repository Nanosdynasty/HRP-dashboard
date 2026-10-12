# Components

The application is server-rendered vanilla HTML/CSS/JS; it has no framework component library. The reusable primitives are CSS classes and the News Intelligence renderer in `static/js/app.js`.

## News Intelligence renderer

Source: `static/js/app.js`

```js
// Dynamic cards are composed from an article source, its relevance reason,
// publication time, topic tags and publisher link. The visual layout is
// controlled by .news-feed, .news-lead and .news-row in style.css.
const image = lead.image_url ? `<img src="${escapeAttr(lead.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" />` : "";
const leadLink = lead.link ? `<a class="news-link" href="${escapeAttr(lead.link)}" target="_blank" rel="noopener noreferrer">Read original coverage</a>` : "";
```
