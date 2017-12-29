import Vue from 'vue';
import Picker from './picker.js'
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
      info: window.app.tags,
    }
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
          unread = unread + i.unread
        }
      }
      return `🏷 ${this.optsInfo.length} tags… (${unread})`;
    }
  },
  methods: {
    update: function(val) {
      this.openInMain(this.info[val])
    },
    display: function(val) {
      let tag = this.info[val];
      return `
        <div class="${tag.unread ? 'tags__item--unread' : ''}">
        ${tag.name}<div class="tags__item__unread">${tag.unread}</div>
        </div>
      `
    },
    filter: function(val, filter) {
      return this.info[val].name.toLowerCase().indexOf(filter.toLowerCase()) != -1
    }
  }
};

Vue.component('tags', Tags);
Vue.component('tags-select', TagsSelect);
