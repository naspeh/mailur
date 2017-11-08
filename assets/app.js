import Vue from 'vue';
import tpl from './app.html';

export default () => {
  window.app = new Vue({
    el: '#app',
    template: tpl,
    data: {
      query: decodeURIComponent(location.hash.slice(1)) || 'all',
      threads: false
    },
    created: function() {
      this.fetch();
    },
    methods: {
      fetch: function(query) {
        if (query) {
          this.query = query;
        }
        window.location.hash = this.query;
        this.$nextTick(() => this.$refs.msgs.fetch());
      }
    }
  });
};
