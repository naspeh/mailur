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
    let name = window.localStorage.getItem('filters') || 'auto';
    return {
      filters: window.data.filters,
      name: name,
      body: window.data.filters[name],
      running: false
    };
  },
  created: function() {
    this.update(this.name);
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
      this.running = true;
      let data = {
        name: this.name,
        body: this.body,
        query: this.query,
        action: 'run'
      };
      this.call('post', '/filters', data)
        .then(() => {
          this.running = false;
          this.refresh();
        })
        .catch(() => (this.running = false));
    },
    save: function() {
      this.running = true;
      let data = {
        name: this.name,
        body: this.body,
        query: this.query,
        action: 'save'
      };
      this.call('post', '/filters', data).then(res => {
        this.running = false;
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
