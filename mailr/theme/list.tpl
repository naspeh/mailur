<ul class="emails">
{% for email in emails %}
    <li class="email">
        <span class="email-from" title="{{ ', '.join(email.from_)|e }}">
            {{ email.from_|map('get_addr_name')|join(', ') }}
        </span>
        {#
        <span class="email-pics">
        {% for addr in email.from_ %}
            <img src="{{ addr|get_gravatar }}?s=20"  alt="{{ addr|e }}" />
        {% endfor %}
        </span>
        #}
        <span class="email-subject">
            {{ email.subject }}
        </span>
        <span class="email-date" title="{{ email.date|format_dt }}">
            {{ email.date|humanize_dt }}
        </span>
    </li>
{% endfor %}
</ul>
