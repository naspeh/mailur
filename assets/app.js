import Vue from 'vue';
import { send } from './utils.js';
import tpl from './app.html';
import './app.css';

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
      side: false
    };
  },
  created: function() {
    window.app = this;
  },
  computed: {
    allTags: function() {
      let tags = [];
      for (let i in this.tags) {
        if (this.tags[i].unread) {
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
    searchTag: function(id) {
      return this.$refs.main.searchTag(id);
    },
    openInSide: function(query) {
      this.side = true;
      this.$nextTick(() => {
        this.$refs.side.fetch(query);
      });
      return;
    },
    toggleSide: function() {
      this.side = !this.side;
      this.$nextTick(() => {
        if (this.side) {
          this.$refs.side.fetch(this.query);
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
