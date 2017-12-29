import Vue from 'vue';
import { contains } from './utils.js';
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
  data: function() {
    return {
      info: window.app.tags
    };
  },
  computed: {
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
    title: function() {
      let unread = 0;
      for (let i of this.optsInfo) {
        if (i.unread) {
          unread = unread + i.unread;
        }
      }
      return `🏷 ${this.optsInfo.length} tags… (${unread})`;
    }
  },
  methods: {
    update: function(val) {
      this.openInMain(this.info[val]);
    },
    display: function(val) {
      let tag = this.info[val];
      let name = this.trancated ? tag['short_name'] : tag['name'];
      return `
        <div class="${tag.unread ? 'tags__item--unread' : ''}">
        ${name}<div class="tags__item__unread">${tag.unread}</div>
        </div>
      `;
    },
    filter: function(val, filter) {
      return contains(this.info[val].name, filter);
    }
  }
};

let TagsEdit = {
  template: tpl,
  mixins: [Tags],
  props: {
    name: { type: String, default: 'tags-edit' },
    picked: { type: Array, required: true },
    edit: { type: Function, required: true },
    opts: { type: Array, default: () => window.app.tagIds }
  },
  data: function() {
    return {
      changed: this.picked.slice()
    };
  },
  watch: {
    picked: function() {
      this.changed = this.picked.slice();
    }
  },
  computed: {
    title: function() {
      return `🏷 ${this.changed.length} tags ${
        this.noChanges ? 'applied' : 'selected'
      }`;
    },
    noChanges: function() {
      if (this.picked.length == this.changed.length) {
        let changed = this.changed.sort();
        let picked = this.picked.slice().sort();
        return picked.every((v, i) => v === changed[i]);
      }
      return false;
    }
  },
  methods: {
    update: function(id) {
      let idx = this.changed.indexOf(id);
      if (idx == -1) {
        this.changed.push(id);
      } else {
        this.changed.splice(idx, 1);
      }
    },
    display: function(id) {
      let tag = this.info[id];
      let checked = this.changed.indexOf(id) != -1 ? 'checked' : '';
      return `
        ${tag.name}<input class="tags__pick" type="checkbox" ${checked} />
      `;
    },
    filter: function(val, filter) {
      return contains(this.info[val].name, filter);
    },
    apply: function() {
      if (this.noChanges) return;
      this.edit({ old: this.picked, new: this.changed });
      this.$refs.picker.cancel(true);
    }
  }
};

Vue.component('tags', Tags);
Vue.component('tags-select', TagsSelect);
Vue.component('tags-edit', TagsEdit);
