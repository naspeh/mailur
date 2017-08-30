### Mailur aims to become a powerful Gmail-inspired webmail.

New version is a rewriting once again with [Dovecot](https://www.dovecot.org/) as a main storage. I've been researching and experimenting with Dovecot several months already and I found some solutions for support tags and pretty fast thread searchers and views, hope I'll finish it someday.

**There is no complete demo yet, still work in progress.**

### Dovecot, really?
- it's already part of email stack with lot of integrations
- it's well designed for emails, so should be efficient
- it has [dsync](https://wiki2.dovecot.org/Tools/Doveadm/Sync), which can be used for master-master replication and to host Mailur locally in the future (for offline usage)
- it has [Sieve](https://wiki2.dovecot.org/Pigeonhole/Sieve) support for filtering e-mail messages

It has some limitations for sure, but seems it's worth it.

I love Gmail labels, it means that you have one big mailbox with all messages and many labels can be applied to one message, IMAP does not support them by default and this is the biggest challenge (some discussions in Dovecot channel: [one](https://www.dovecot.org/pipermail/dovecot/2013-March/089275.html), [two](https://www.dovecot.org/list/dovecot/2017-January/106650.html)).

#### Mailboxes
- **Src** - mailbox with all original messages (probably can be `INBOX`), labels are saved as IMAP Keywords (user-defined flags), but as keywords have limitation (for example: only Latin letters,no spaces), so next mailbox appears...
- **Tags** - mailbox contains all tags (or labels) saved as emails and `UID` uses to identify IMAP keywords with particular tag (so IMAP keywords look like `#t1`, `#t2`). Also additional information can be saved in related email: like color, etc.
- **All** - mailbox contains prepared messages, so each original message parsed once and saved in usable form, so attachments will be extracted and saved to serve them via HTTP, also `UID` for original message from **Src** saved in parsed message too.
- **Spam** - mailbox as **All** has parsed messages, but those messages are marked as spam.
- **Trash** - mailbox as **Spam**, but those messages are marked as deleted.

Dovecot has support of [THREAD Extension](https://tools.ietf.org/html/rfc5256) so **All** mailbox is separated from **Spam** and **Trash** for easy thread searches.

This additional transformation from original to parsed (prepared) message can be used for decryption in the future...

#### What is ready?
- Import from Gmail. Tested on mailbox with ~100k emails: takes ~1hour. It was needed to experiment with built-in Dovecot search and other functionality.
- Basic parsing from original to prepared state. There is also an additional step for marking latest messages in threads for faster API endpoints. It still needs attachment extraction, etc.
- Basic HTTP application with some "must have" endpoints.
- There are some good tests exist and the basis to write them further, for example Dovecot has been used for mocking Gmail IMAP...

All this stuff was needed to answer the main question:
* Is it possible to implement fast webmail using Dovecot as main storage?

So now I can say:
* Yes, I'm going to work further on this.

### Previous versions:
- **0.1** | Apr 2014 | [code](https://github.com/naspeh/mailur/tree/0.1) | [post](https://pusto.org/mailur/intro/) | The first prototype.
- **0.2** | Nov 2015 | [code](https://github.com/naspeh/mailur/tree/0.2) | [post](https://pusto.org/mailur/alpha/) | The alpha version (I've still using it by now on daily basis).
