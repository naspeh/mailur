import Vue from 'vue';
import { send } from './utils.js';
import tpl from './app.html';

Vue.component('App', {
  template: tpl,
  props: {
    _query: { type: String, required: true },
    _tags: { type: Object, default: {} }
  },
  data: function() {
    return {
      query: this._query,
      tags: this._tags,
      split: false
    };
  },
  created: function() {
    window.app = this;
  },
  computed: {
    allTags: function() {
      let tags = [];
      for (let i in this.tags) {
        let tag = this.tags[i];
        if (tag.unread || tag.pinned) {
          tags.push(i);
        }
      }
      return tags;
    }
  },
  watch: {
    query: function(val) {
      window.location.hash = val;
    }
  },
  methods: {
    fetch: function(q) {
      return this.$refs.main.fetch(q);
    },
    openInSplit: function(query) {
      this.split = true;
      this.$nextTick(() => {
        this.$refs.split.fetch(query);
      });
      return;
    },
    toggleSplit: function() {
      this.split = !this.split;
      this.$nextTick(() => {
        if (this.split) {
          this.$refs.split.fetch(this.query);
        }
      });
    }
  }
});

export default function() {
  let q = decodeURIComponent(location.hash.slice(1));
  if (!q) {
    q = ':threads keyword #inbox';
    window.location.hash = q;
  }

  let data = {
    offset: new Date().getTimezoneOffset() / 60
  };
  send('/init', data).then(res => {
    new Vue({
      el: '#app',
      template: '<app v-bind="init" />',
      data: {
        init: {
          _query: q,
          _tags: res.tags
        }
      }
    });
  });
}
