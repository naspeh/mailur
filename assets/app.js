import Vue from 'vue';
import { send } from './utils.js';
import tpl from './app.html';

Vue.component('App', {
  template: tpl,
  data: function() {
    return {
      query: '',
      threads: false,
      tags: {}
    };
  },
  created: function() {
    window.app = this;
    this.setQuery();
    return this.send('/init', {
      offset: new Date().getTimezoneOffset() / 60
    }).then(res => {
      this.tags = res.tags;
      this.fetch();
    });
  },
  methods: {
    send: send,
    setQuery: function(query) {
      if (query) {
        this.query = query;
      } else if (this.query) {
        // pass
      } else {
        let q = decodeURIComponent(location.hash.slice(1));
        if (q) {
          this.query = q;
        } else {
          this.query = ':threads keyword #inbox';
        }
      }
      window.location.hash = this.query;
    },
    fetch: function(query) {
      this.setQuery(query);
      this.$nextTick(() => this.$refs.msgs.fetch());
    },
    searchHeader: function(name, value) {
      value = JSON.stringify(value);
      return this.fetch(`:threads header ${name} ${value}`);
    },
    searchTag: function(tag) {
      let q;
      if (tag[0] == '\\') {
        q = tag.slice(1);
      } else {
        tag = JSON.stringify(tag);
        q = `keyword ${tag}`;
      }
      q = ':threads ' + q;
      return this.fetch(q);
    },
    searchAddr: function(addr) {
      this.fetch(`:threads from ${addr}`);
    },
    thread: function(uid) {
      return this.fetch(`inthread refs uid ${uid}`);
    }
  }
});
