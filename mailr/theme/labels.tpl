{% if labels %}
<select class="labels">
{% for label in labels %}
    <option value="{{ label.url }}" data-id="{{ label.id }}">
        {{ label.human_name }} <b>{{ label.unread }}</b>/{{ label.exists }}
    </option>
{% endfor %}
</select>
{#<button name="compose" class="btn-compose">Compose</button>#}
<div class="loader-fixed">Loading..</div>
{% endif %}
