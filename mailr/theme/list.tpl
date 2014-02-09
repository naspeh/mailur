<ul class="emails">
{% for email in emails %}
    <li class="email">
        <span class="email-from" title="{{ ', '.join(email.from_)|e }}">
            {{ ', '.join(email.names_from)|e }}
        </span>
        <span class="email-subject">
            {{ email.subject }}
        </span>
        <span class="email-date" title="{{ email.date }}">
            {{ email.human_date }}
        </span>
    </li>
{% endfor %}
</ul>
