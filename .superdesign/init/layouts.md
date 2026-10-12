# Layouts

## Application shell

Source: `static/index.html`

The dashboard uses a persistent left filter/sidebar plus full-height workspace surfaces. News Intelligence is an absolute, scrollable surface mounted inside the main workspace. It includes a sticky header, horizontal topic controls, a KPI strip and a dynamic article feed.

```html
<section id="news-surface" class="news-surface" hidden>
  <header class="news-surface-header">...</header>
  <nav id="news-topic-tabs" class="news-topic-tabs">...</nav>
  <div id="news-metrics" class="news-metrics"></div>
  <div id="news-feed" class="news-feed"></div>
</section>
```
