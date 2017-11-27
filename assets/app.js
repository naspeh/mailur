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
    return this.send('/login', {
      offset: new Date().getTimezoneOffset() / 60
    }).then(() => this.fetch());
  },
  computed: {
    url: function() {
      return this.threads ? '/thrs' : '/msgs';
    }
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
        if (q && q.indexOf('/msgs/') == 0) {
          this.query = q.slice(6);
          this.threads = false;
        } else if (q && q.indexOf('/thrs/') == 0) {
          this.query = q.slice(6);
          this.threads = true;
        } else {
          this.query = 'all';
        }
      }
      window.location.hash = `${this.url}/${this.query}`;
    },
    fetch: function(query) {
      this.setQuery(query);
      this.$nextTick(() => {
        this.send('/tags')
          .then(res => (this.tags = res))
          .then(() => this.$refs.msgs.fetch());
      });
    },
    searchHeader: function(name, value) {
      value = JSON.stringify(value);
      return this.fetch(`header ${name} ${value}`);
    },
    searchTag: function(tag) {
      let q;
      if (tag[0] == '\\') {
        q = tag.slice(1);
      } else {
        tag = JSON.stringify(tag);
        q = `keyword ${tag}`;
      }
      this.threads = true;
      return this.fetch(q);
    },
    thread: function(uid) {
      this.threads = false;
      return this.fetch(`inthread refs uid ${uid}`);
    }
  }
});
