import React from 'react';

export const ColonelLogo = ({ className = "w-8 h-8" }) => (
  <img 
    src="/the-colonel-logo.png" 
    alt="The Colonel" 
    className={`${className} object-contain`}
  />
);

export const MagicUnicornLogo = ({ className = "w-6 h-6" }) => (
  <img 
    src="/magic-unicorn-logo.png" 
    alt="Magic Unicorn" 
    className={`${className} object-contain`}
  />
);

export const CenterDeepLogo = ({ className = "w-8 h-8" }) => (
  <img 
    src="/center-deep-logo.png" 
    alt="Center Deep" 
    className={`${className} object-contain`}
  />
);