import Vue from 'vue';
import { contains, call } from './utils.js';
import tpl from './tags.html';

let Tags = {
  template: tpl,
  props: {
    opts: { type: Array, required: true },
    trancated: { type: Boolean, default: false },
    unread: { type: Boolean, default: false },
    edit: { type: Function },
    name: { type: String, default: 'tags' }
  },
  computed: {
    info: function() {
      this.opts || true;
      return window.app.tags;
    },
    optsInfo: function() {
      let tags = [];
      for (let id of this.opts) {
        tags.push(this.info[id]);
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
};

let TagsSelect = {
  template: tpl,
  mixins: [Tags],
  props: {
    name: { type: String, default: 'tags-select' }
  },
  computed: {
    totalUnread: function() {
      let unread = 0;
      for (let i of this.optsInfo) {
        if (i.unread) {
          unread = unread + i.unread;
        }
      }
      return unread;
    }
  },
  methods: {
    tagName: function(id) {
      return this.trancated ? this.info[id].short_name : this.info[id].name;
    },
    update: function(val) {
      this.openInMain(this.info[val]);
    },
    filter: function(val, filter) {
      return contains(this.info[val].name, filter);
    }
  }
};

let TagsEdit = {
  template: tpl,
  mixins: [TagsSelect],
  props: {
    name: { type: String, default: 'tags-edit' },
    origin: { type: Array, required: true },
    edit: { type: Function, required: true },
    opts: { type: Array, default: () => window.app.tagIds }
  },
  data: function() {
    return {
      new: {},
      picked: null,
      failed: null
    };
  },
  created: function() {
    this.cancel();
  },
  watch: {
    origin: function() {
      this.cancel();
    }
  },
  computed: {
    info: function() {
      this.opts || true;
      let info = window.app.tags;
      for (let i in this.new) {
        if (info[i]) {
          delete this.new[i];
        }
      }
      return Object.assign({}, this.new, info);
    },
    noChanges: function() {
      if (this.origin.length == this.picked.length) {
        let picked = this.picked.sort();
        let origin = this.origin.slice().sort();
        return origin.every((v, i) => v === picked[i]);
      }
      return false;
    },
    sort: function() {
      let tags = this.picked.slice();
      tags = tags.concat(this.opts.filter(i => this.picked.indexOf(i) == -1));
      this.$nextTick(
        () => this.$refs.picker.active && this.$refs.picker.activate()
      );
      return tags;
    }
  },
  methods: {
    tagChecked: function(id) {
      return this.picked.indexOf(id) != -1;
    },
    cancel: function() {
      this.picked = this.origin.slice();
      this.failed = null;
    },
    update: function(id) {
      if (this.opts.indexOf(id) == -1) {
        call('post', '/tag', { name: id }).then(res => {
          if (res.errors) {
            this.failed = id;
            this.$refs.picker.filter = id;
            return;
          }
          this.new[res.id] = res;
          this.new = Object.assign({}, this.new);
          this.opts.splice(0, 0, res.id);
          this.update(res.id);
        });
        return;
      }
      let idx = this.picked.indexOf(id);
      if (idx == -1) {
        this.picked.push(id);
      } else {
        this.picked.splice(idx, 1);
      }
    },
    apply: function() {
      if (this.noChanges) return;
      this.edit({ old: this.origin, new: this.picked }).then(() =>
        window.app.refreshTags()
      );
      this.$refs.picker.cancel(true);
    }
  }
};

Vue.component('tags', Tags);
Vue.component('tags-select', TagsSelect);
Vue.component('tags-edit', TagsEdit);
