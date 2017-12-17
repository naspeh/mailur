import Vue from 'vue';
import './msgs.js';
import './tags.js';
import tpl from './page-index.html';

Vue.component('App', {
  template: tpl,
  data: function() {
    return {
      tags: window.data.tags,
      query: null,
      split: false,
      bigger: false
    };
  },
  created: function() {
    window.app = this;

    let q = decodeURIComponent(location.hash.slice(1));
    if (!q) {
      q = ':threads keyword #inbox';
      window.location.hash = q;
    }
    this.query = q;
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
    },
    toggleBigger: function() {
      this.bigger = !this.bigger;
    },
    logout: function() {
      window.location = '/logout';
    }
  }
});

new Vue({
  el: '#app',
  template: '<app />'
});
