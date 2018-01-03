import Vue from 'vue';
import { call } from './utils.js';
import './picker.js';
import './tags.js';
import './msg.js';
import msgs from './msgs.js';
import tpl from './app.html';

Vue.component('app', {
  template: tpl,
  data: function() {
    return {
      tags: window.data.tags.info,
      tagIds: window.data.tags.ids,
      addrs: [],
      picSize: 20,
      tagCount: 7,
      opts: { split: false, splitQuery: null, bigger: false },
      optsKey: `${window.data.user}:opts`
    };
  },
  created: function() {
    let opts = window.localStorage.getItem(this.optsKey);
    if (opts) {
      this.opts = JSON.parse(opts);
      this.reloadOpts();
    }

    window.app = this;
    this.openFromHash();

    window.onhashchange = () => {
      this.openFromHash();
    };
  },
  computed: {
    allTags: function() {
      let tags = [];
      for (let i of this.tagIds) {
        let tag = this.tags[i];
        if (tag.unread || tag.pinned) {
          tags.push(i);
        }
      }
      return tags;
    }
  },
  methods: {
    setOpt: function(name, value) {
      this.opts[name] = value;
      window.localStorage.setItem(this.optsKey, JSON.stringify(this.opts));
      this.reloadOpts();
    },
    toggleOpt: function(name) {
      this.setOpt(name, !this.opts[name]);
    },
    reloadOpts: function() {
      document
        .querySelector('html')
        .classList.toggle('opt--bigger', this.opts.bigger);
      if (!this.split && this.opts.split && this.opts.splitQuery) {
        this.openInSplit(this.opts.splitQuery);
      }
    },
    openFromHash: function() {
      let q = decodeURIComponent(location.hash.slice(1));
      if (!q) {
        q = ':threads keyword #inbox';
      }
      if (!this.main || this.main.query != q) {
        this.openInMain(q);
      }
    },
    search: function(q, preload = undefined) {
      return call('post', '/search', { q: q, preload: preload });
    },
    openInMain: function(q) {
      this.main && this.main.clean();
      this.search(q).then(res => {
        window.location.hash = q;
        this.main = msgs(
          Object.assign(res, {
            cls: 'main',
            query: q,
            open: this.openInMain,
            search: this.search,
            pics: this.pics
          })
        );
      });
    },
    openInSplit: function(q) {
      this.opts.split || this.setOpt('split', true);
      this.opts.splitQuery == q || this.setOpt('splitQuery', q);
      this.split && this.split.clean();
      this.search(q).then(res => {
        this.split = msgs(
          Object.assign(res, {
            cls: 'split',
            query: q,
            open: this.openInSplit,
            search: this.search,
            pics: this.pics
          })
        );
      });
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
