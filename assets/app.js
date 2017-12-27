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
    this.openInMain(q);
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
    search: function(q, preload = undefined) {
      return call('post', '/search', { q: q, preload: preload });
    },
    openInMain: function(q) {
      this.main && this.main.clean();
      this.search(q).then(res => {
        window.location.hash = q;
        this.main = msgs(
          Object.assign(res, {
            cls: 'main__body',
            query: q,
            open: this.openInMain,
            search: this.search,
            pics: this.pics
          })
        );
      });
    },
    openInSplit: function(q) {
      this.optSplit = true;
      this.split && this.split.clean();
      this.search(q).then(res => {
        this.split = msgs(
          Object.assign(res, {
            cls: 'split__body',
            query: q,
            open: this.openInSplit,
            search: this.search,
            pics: this.pics
          })
        );
      });
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
