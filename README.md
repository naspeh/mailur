## [Mailur] is a lightweight webmail inspired by Gmail

## Features
- multiple tags for messages (no folders)
- [manually linking threads](https://pusto.org/mailur/features/#link-threads)
- [Sieve scripts for email filtering](https://pusto.org/mailur/features/#sieve-scripts)
- [composing messages with Markdown](https://pusto.org/mailur/features/#markdown)
- [independent split pane](https://pusto.org/mailur/features/#the-split-pane)
- easy to switch from threads view to messages view
- slim and compact interface with few basic themes
- ...

Brand-new version uses [Dovecot as main storage][mlr-dovecot], no database required.

This version is already in use. It has minimal feature set I need on daily basis. I have big plans for this project and I'm still working on it when I have spare time.

### Related links
- [public demo][demo] (credentials: demo/demo)
- [installation][install]

![Screenshots](https://pusto.org/mailur/features/the-split-pane.gif)

[Mailur]: https://pusto.org/mailur/
[demo]: http://demo.pusto.org
[install]: https://pusto.org/mailur/installation/
[vimeo]: https://vimeo.com/259140545
[mlr-dovecot]: https://pusto.org/mailur/dovecot/
[mlr-features]: https://pusto.org/mailur/features/
[Markdown]: https://daringfireball.net/projects/markdown/syntax

### Updates
- `[Nowadays]` Stay tuned...
- `[May 2020]` Two-way syncing for five Gmail flags and labels (details here [#13])
- `[Mar 2019]` [Feature overview.][mlr-features]
- `[Mar 2019]` [Dovecot as main storage.][mlr-dovecot]
- `[Nov 2015]` [`code`][v02code] [The alpha version.][v02post] Postgres based. We used it over 2 years on daily basis.
- `[Apr 2014]` [`code`][v01code] [The first prototype.][v01post]

[#13]: https://github.com/naspeh/mailur/issues/13
[v02code]: https://github.com/naskoro/mailur-pg
[v02post]: https://pusto.org/mailur/alpha/
[v01code]: https://github.com/naskoro/mailur-pg/tree/prototype
[v01post]: https://pusto.org/mailur/intro/
