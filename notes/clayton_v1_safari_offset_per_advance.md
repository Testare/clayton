## FEAT: New model paremeter: safari_offset_per_advance

This is a change to claytonlib itself more than just the app, but this is an important feature we need. I don't have strong data to support its necessity just yet, but let's build it in and it hopefully won't make things WORSE.

I believe that the more Seed A advances the user makes, the user experiences a certain amount of lost frames when attempting to hit Seed B, making the delay lower than expected with more advances. So we should add a variable, safari_offset_per_advance, that is multiplied by the number of seed a advances done when calculating what frame we expect to hit. I'm intending to gather data to try and support this theory using the app, so let's just build it in now. 

In case this model isn't correct, we can add a checkbox option in the calibrate model page for Safari Compass that calcultes things the current way, and forces this parameter to zero. This setting should be saved to the expedition so if the user prefers one or the other, they don't have to keep clicking the checkbox.

This parameter should be used when using Safari Chart to find targets (Using key seed advances as input), as well as when calculating Seed B candidate seeds (Since we find the number of advances in the previous step anyways). If the user doesn't want this behavior, they can use a model that is calibrated with the setting that forces this value to zero, which would mean it doesn't matter that it is an input anyways.

I think it might be more closely related to chatot flips than elm call advances, but the number of elm calls the user makes is relatively stable compared to the number of chatot flips they make each run, so the safari_offset_per_advance and normal safari_offset should be enough to cover that.

Is it reasonable to try and calculate this value, as well as safari_offset (and related paremeters), from safari runs? Any concerns with doing this?
