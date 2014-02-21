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

        {% if email.labels %}
        <span class="email-labels">
        {% for label in email.full_labels if not label.is_folder %}
            <a href="#{{ url_for('label', id=label.id) }}">{{ label.name }}</a>
        {% endfor %}
        </span>
        {% endif %}

        <span class="email-subject">
        {% if 'thread' in request.path %}
            <a href="{{ url_for('raw', id=email.id) }}" target="_blank">{{ email.subject }}</a>
        {% elif request.args.get('gm') %}
            <a href="#{{ url_for('gm_thread', id=email.gm_thrid) }}">{{ email.subject }}</a>
        {% else %}
            <a href="#{{ url_for('thread', id=email.uid) }}">{{ email.subject }}</a>
        {% endif %}
        </span>

        <span class="email-date" title="{{ email.date|format_dt }}">
            {{ email.date|humanize_dt }}
        </span>
    </li>
{% endfor %}
</ul>
