// Setup polyfills
require('whatwg-fetch');
require('core-js/fn/set');
require('core-js/fn/symbol');
require('core-js/fn/array');

export let array_union = require('lodash/array/union');

// Ref: http://stackoverflow.com/questions/105034/create-guid-uuid-in-javascript
export function guid() {
    var d = new Date().getTime();
    var uuid = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(
        /[xy]/g,
        (c) => {
            var r = (d + Math.random() * 16) % 16 | 0;
            d = Math.floor(d / 16);
            return (c == 'x' ? r : (r & 0x3 | 0x8)).toString(16);
        });
    return uuid;
}
