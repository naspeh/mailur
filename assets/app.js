import Vue from 'vue';
import { call } from './utils.js';
import './tags.js';
import './msg.js';
import msgs from './msgs.js';
import tpl from './app.html';

Vue.component('app', {
  template: tpl,
  data: function() {
    return {
      tags: window.data.tags,
      addrs: [],
      picSize: 20,
      optSplit: false,
      optBigger: false
    };
  },
  created: function() {
    window.app = this;

    let q = decodeURIComponent(location.hash.slice(1));
    if (!q) {
      q = ':threads keyword #inbox';
    }
    this.fetch(q);
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
  methods: {
    call: call,
    fetch: function(q, opts) {
      opts = opts || {};
      let result = this.call('post', '/search', {
        q: q,
        preload: opts.preload
      });
      if (!opts.refresh) {
        if (opts.split) {
          this.split && this.split.clean();
        } else {
          this.main && this.main.clean();
        }
        result.then(res => {
          let view = msgs(
            Object.assign(res, {
              cls: `${opts.split ? 'split' : 'main'}__body`,
              query: q,
              fetch: opts.split ? this.openInSplit : this.fetch,
              pics: this.pics
            })
          );

          if (opts.split) {
            this.split = view;
          } else {
            this.main = view;
            window.location.hash = q;
          }
        });
      }
      return result;
    },
    openInSplit: function(query) {
      this.optSplit = true;
      this.fetch(query, { split: true });
    },
    toggleSplit: function() {
      this.optSplit = !this.optSplit;
      this.$nextTick(() => {
        if (this.optSplit && !this.split) {
          this.openInSplit(this.main.query);
        }
      });
    },
    toggleBigger: function() {
      this.bigger = !this.bigger;
    },
    logout: function() {
      window.location = '/logout';
    },
    pics: function(msgs) {
      let hashes = [];
      for (let m in msgs) {
        for (let f of msgs[m].from_list) {
          if (
            f.hash &&
            hashes.indexOf(f.hash) == -1 &&
            this.addrs.indexOf(f.hash) == -1
          ) {
            hashes.push(f.hash);
          }
        }
      }
      if (hashes.length == 0) {
        return;
      }
      this.addrs = this.addrs.concat(hashes);
      while (hashes.length > 0) {
        let sheet = document.createElement('link');
        let few = encodeURIComponent(hashes.splice(0, 50));
        sheet.href = `/avatars.css?size=${this.picSize}&hashes=${few}`;
        sheet.rel = 'stylesheet';
        document.body.appendChild(sheet);
      }
    }
  }
});

new Vue({
  el: '#app',
  template: '<app />'
});
