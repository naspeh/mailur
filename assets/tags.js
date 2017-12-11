import Vue from 'vue';
import tpl from './tags.html';
import './tags.css';

Vue.component('Tags', {
  template: tpl,
  props: {
    trancated: { type: Boolean, default: false },
    unread: { type: Boolean, default: false },
    raw: { type: Array, required: true }
  },
  computed: {
    display: function() {
      let tags = [];
      for (let id of this.raw) {
        tags.push(window.app.tags[id]);
      }
      return tags;
    }
  },
  methods: {
    fetch: tag => window.app.fetch(tag.query)
  }
});
