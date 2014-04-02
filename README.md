**Mailr** is an Open Source webmail client with gmail like conversations.

**Note.** Mailr is at the beginning of development. There is a lot of work, that has to be 
done.

Here is more information http://pusto.org/en/mailr/.

Here is **public demo** http://mail.pusto.org, you can send email to 
**mailr[at]pusto.org** and it probably appears in Inbox.

###Screenshot

![Mailr Screenshot](http://pusto.org/en/mailr/screenshot-s.png)

###Installation

Requires Python>=3.3 and PostgreSQL.

```
$ pip install -r requiremets.txt

# Create database with hstore extension
> CREATE DATABASE mailr WITH OWNER mailr;
> CREATE EXTENSION hstore;
$ ./manage.py db-init

$ cp conf_test.json conf.json
# Then fix "google_id", "google_secret", "email" and "pg_*" settings

$ ./manage.py run
# Go to http://localhost:5000/auth/ for getting auth token from google

# Then synchronize all emails
$ ./manage.py sync -b

# Then you can see your emails in Mailr
$ ./manage.py run
```
