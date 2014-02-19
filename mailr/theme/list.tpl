<ul class="emails">
{% for email in emails %}
    <li class="email{% if email.unread %} email-unread{% endif %}">
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
        {% if email.starred %}
        <span class="email-star">*</span>
        {% endif %}
        <span class="email-labels">
        {% for label in email.full_labels if not label.is_folder %}
            <a href="#{{ url_for('label', id=label.id) }}">{{ label.name }}</a>
        {% endfor %}
        </span>
        <span class="email-subject">
            <a href="{{ url_for('raw', id=email.id) }}" target="_blank">
                {{ email.subject }}
            </a>
        </span>
        <span class="email-date" title="{{ email.date|format_dt }}">
            {{ email.date|humanize_dt }}
        </span>
    </li>
{% endfor %}
</ul>
