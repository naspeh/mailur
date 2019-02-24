import Vue from 'vue';
import tpl from './filters.html';

Vue.component('filters', {
  template: tpl,
  props: {
    query: { type: String, required: true },
    call: { type: Function, required: true },
    refresh: { type: Function, required: true }
  },
  data: function() {
    return {
      filters: null,
      name: window.localStorage.getItem('filters') || 'auto',
      body: ''
    };
  },
  created: function() {
    this.call('get', '/filters').then(res => {
      this.filters = res;
      this.update(this.name);
    });
  },
  methods: {
    update: function(name) {
      this.name = name;
      window.localStorage.setItem('filters', name);
      let autosaved = window.localStorage.getItem(this.storageKey());
      this.body = autosaved || this.filters[name];
      return name;
    },
    storageKey: function(name) {
      name = name || this.name;
      return 'filters:' + name;
    },
    autosave: function() {
      window.localStorage.setItem(this.storageKey(), this.body);
    },
    run: function() {
      let data = {
        name: this.name,
        body: this.body,
        query: this.query,
        action: 'run'
      };
      this.call('post', '/filters', data).then(() => {
        this.refresh();
      });
    },
    save: function() {
      let data = {
        name: this.name,
        body: this.body,
        query: this.query,
        action: 'save'
      };
      this.call('post', '/filters', data).then(res => {
        window.localStorage.removeItem(this.storageKey());
        this.filters = res;
        this.update(this.name);
      });
    },
    cancel: function() {
      window.localStorage.removeItem(this.storageKey());
      this.update(this.name);
    },
    close: function() {
      window.app.toggleOpt('filters');
    }
  }
});
