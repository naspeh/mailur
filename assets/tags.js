import Vue from 'vue';
import tpl from './tags.html';

Vue.component('tags', {
  template: tpl,
  props: {
    raw: { type: Array, required: true },
    trancated: { type: Boolean, default: false },
    unread: { type: Boolean, default: false },
    edit: { type: Function }
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
    openInMain: tag => window.app.openInMain(tag.query),
    remove: function(tag) {
      return this.edit({ old: [tag] });
    }
  }
});
