import Vue from 'vue';
import tpl from 'html-loader!./app.html';

export default () => {
  window.app = new Vue({
    el: '#app',
    template: tpl,
    data: {
      query: decodeURIComponent(location.hash.slice(1)) || 'all',
      showBodies: false,
      showThreads: false
    },
    methods: {
      get: function() {
        window.location.hash = this.query;
        this.$refs.msgs.get(
          this.showThreads ? '/api/threads' : '/api/msgs',
          this.query
        );
      }
    }
  });
};
